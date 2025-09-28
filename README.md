# github_status

Jerry's technical assessment submission for GitHub Status

- **Email:** jerryohjieyi1995@gmail.com  
- **LinkedIn:** [Jerry Oh Jie Yi](https://www.linkedin.com/in/jerry-oh-jie-yi-548524190/)  

**Submission:** [Jerry - GitHub Status Dashboard](https://d1insua5ixvm3k.cloudfront.net/)

---

## Architecture Diagram

<img width="521" height="642" alt="GithubStatusArchi_v1" src="https://github.com/user-attachments/assets/a4f00416-8739-4717-90cc-6534464904eb" />

The Lambda function is triggered by EventBridge every 4 hours to retrieve GitHub status, incidents, and maintenance information through the API.  
It is placed in the private subnet together with the database, and routes traffic through the NAT gateway in the public subnet to access the internet and Secrets Manager for the RDS credentials.  

The web application is deployed in the public subnet and can only be accessed through CloudFront, which has WAF attached to it.  
Direct access to the ALB or instances is not allowed. This restriction is enforced through the security group configuration.

---

## Codes

- Implemented mainly in **Python**, as I am more familiar with it.   
- Lambda - **insert_into_db** runs on **Python 3.11** with the **psycopg2** package attached as a layer. psycopg2 is used as the database engine.  
- Utilizes environment variables and AWS Secrets Manager so that credentials are not exposed.  
- The web application is built with **Python Flask**:  
  - `github-status/app.py`  
  - `github-status/templates/index.html`  
